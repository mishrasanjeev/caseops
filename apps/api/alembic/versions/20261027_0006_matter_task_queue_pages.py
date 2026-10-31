"""Dense Matter-task pages, maintained for old and current source writers.

Revision ID: 20261027_0006
Revises: 20261027_0005
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged; source write fence, exact lossless group
backfill and trigger installation share the bounded migration transaction.
No Task/outbox/Matter/Member values are changed. SQLite backfill only reads source rows
and does not change timestamps. PostgreSQL parent locks are not added.
MIGRATION-ROLLBACK: restore-forward only; derived retained content remains fenced.
"""

import hashlib
import os
import stat
from pathlib import Path

import sqlalchemy as sa

from alembic import op

revision = "20261027_0006"
down_revision = "20261027_0005"
branch_labels = None
depends_on = None
# Typed immutable source dependency, not a credential or runtime configuration.
SCHEMA_HELPER_SHA256 = "132f299ca614172b5437f51a8477e4bb3be38d7d8b0ed64f1470c034d18f7146"
_SCHEMA_METADATA = (
    "st_dev",
    "st_ino",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
    "st_mode",
    "st_uid",
    "st_gid",
    "st_nlink",
)


def _same_named_descriptor(named, opened, *, windows=False):
    """Pure portability contract; FD-to-FD device checks remain exact."""
    fields = tuple(k for k in _SCHEMA_METADATA if not (windows and k == "st_dev"))
    return (
        stat.S_ISREG(named.st_mode)
        and stat.S_ISREG(opened.st_mode)
        and tuple(getattr(named, k) for k in fields) == tuple(getattr(opened, k) for k in fields)
    )


def _schema_path():
    return Path(__file__).resolve().parents[2] / "src/caseops_api/db/task_queue_page_schema_v1.py"


def _load_schema_v1(io=None):
    """Verify/compile one held buffer; no mutable module/PYC is imported."""
    io = io or os
    path = _schema_path()
    fd = None
    try:
        if path.resolve(strict=True) != path.absolute():
            raise ValueError
        ancestors = {
            p: tuple(getattr(p.lstat(), k) for k in _SCHEMA_METADATA) for p in path.parents
        }
        named = path.lstat()
        if not stat.S_ISREG(named.st_mode) or not 0 < named.st_size <= 131072:
            raise ValueError
        fd = io.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        opened = io.fstat(fd)
        meta = tuple(getattr(opened, k) for k in _SCHEMA_METADATA)
        if not _same_named_descriptor(named, opened, windows=os.name == "nt"):
            raise ValueError
        chunks, total = [], 0
        while total <= 131072:
            chunk = io.read(fd, min(32768, 131073 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        source = b"".join(chunks)
        if (
            total != opened.st_size
            or total > 131072
            or meta != tuple(getattr(io.fstat(fd), k) for k in _SCHEMA_METADATA)
            or tuple(getattr(named, k) for k in _SCHEMA_METADATA)
            != tuple(getattr(path.lstat(), k) for k in _SCHEMA_METADATA)
            or path.resolve(strict=True) != path.absolute()
            or ancestors
            != {p: tuple(getattr(p.lstat(), k) for k in _SCHEMA_METADATA) for p in path.parents}
            or hashlib.sha256(source).hexdigest() != SCHEMA_HELPER_SHA256
        ):
            raise ValueError
        namespace = {"__name__": "caseops_closed_task_queue_schema_v1", "__file__": str(path)}
        exec(compile(source, str(path), "exec"), namespace)
        return namespace
    except Exception:
        raise RuntimeError("TASK_QUEUE_SCHEMA_DEPENDENCY_INVALID") from None
    finally:
        if fd is not None:
            io.close(fd)


def upgrade():
    # Dependency admission precedes even the first database handle/DDL operation.
    schema = _load_schema_v1()
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
        connection.exec_driver_sql("SET LOCAL statement_timeout = '30s'")
        connection.exec_driver_sql("LOCK TABLE matter_tasks IN SHARE ROW EXCLUSIVE MODE")
    # Frozen migration schema, independent of future current ORM additions.
    integer_id = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "matter_task_queue_groups",
        sa.Column("id", integer_id, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("matter_id", sa.String(36), nullable=False),
        sa.Column("owner_is_null", sa.Boolean(), nullable=False),
        sa.Column("owner_key", sa.String(36), nullable=False),
        sa.UniqueConstraint(
            "company_id",
            "matter_id",
            "owner_is_null",
            "owner_key",
            name="uq_matter_task_queue_group_scope",
        ),
        sa.CheckConstraint(
            "(owner_is_null AND owner_key = '') OR NOT owner_is_null",
            name="ck_matter_task_queue_group_owner_key",
        ),
    )
    columns = [
        sa.Column(
            "group_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True
        ),
        sa.Column("page_no", sa.Integer(), primary_key=True),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("has_dated", sa.Boolean(), nullable=False),
        sa.Column("has_undated", sa.Boolean(), nullable=False),
        sa.Column("min_dated", sa.Date()),
        sa.Column("max_dated", sa.Date()),
        sa.Column("last_null", sa.Boolean(), nullable=False),
        sa.Column("last_date", sa.Date(), nullable=False),
        sa.Column("last_created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_id", sa.String(36), nullable=False),
    ]
    for slot in range(25):
        for name, field_type in (
            ("id", sa.String(36)),
            ("title", sa.Text()),
            ("status", sa.Text()),
            ("priority", sa.Text()),
            ("due_on", sa.Date()),
            ("created_at", sa.DateTime(timezone=True)),
            ("updated_at", sa.DateTime(timezone=True)),
        ):
            columns.append(sa.Column(f"s{slot}_{name}", field_type))
    op.create_table(
        "matter_task_queue_pages",
        *columns,
        sa.PrimaryKeyConstraint(name="pk_matter_task_queue_pages"),
        sa.CheckConstraint("entry_count BETWEEN 1 AND 25", name="ck_matter_task_queue_page_size"),
        sa.CheckConstraint("page_no >= 0", name="ck_matter_task_queue_page_number"),
    )
    op.create_table(
        "matter_task_queue_dirty",
        sa.Column("transaction_id", sa.BigInteger(), primary_key=True),
        sa.Column("company_id", sa.String(36), primary_key=True),
        sa.Column("matter_id", sa.String(36), primary_key=True),
        sa.Column("owner_is_null", sa.Boolean(), primary_key=True),
        sa.Column("owner_key", sa.String(36), primary_key=True),
    )
    schema["install"](connection)
    schema["backfill"](connection)


def downgrade():
    raise RuntimeError("Matter-task queue storage requires reviewed roll-forward or restore.")
