"""Packed retained-read leaves with source-compatible deferred maintenance.

Revision ID: 20261027_0008
Revises: 20261027_0007
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged; source writer fence5s, statement30s.
MIGRATION-ROLLBACK: restore-forward. Downgrade refuses before any DDL/data write.

Only derived storage is added. Original source/audit/outbox bytes are untouched.
Frozen v1 code is shared with metadata.create_all's exact new-schema hook.
This is not a measured400-work or arbitrary restricted-writer-role claim.
"""

import hashlib
import os
import stat
from pathlib import Path

from alembic import op

revision = "20261027_0008"
down_revision = "20261027_0007"
branch_labels = None
depends_on = None


# Typed immutable source dependency, not a credential or runtime configuration.
SCHEMA_HELPER_SHA256 = "16ddca96f88d66c121b01e1d78974b8eb8153652a32a834dfa0a4f5155ce8402"
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
    return (
        Path(__file__).resolve().parents[2]
        / "src/caseops_api/db/matter_readthrough_page_schema_v1.py"
    )


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
        namespace = {"__name__": "caseops_closed_readthrough_schema_v1", "__file__": str(path)}
        exec(compile(source, str(path), "exec"), namespace)
        return namespace
    except Exception:
        raise RuntimeError("READTHROUGH_SCHEMA_DEPENDENCY_INVALID") from None
    finally:
        if fd is not None:
            io.close(fd)


def upgrade():
    # Admit the immutable held source before even the first DB handle.
    schema = _load_schema_v1()
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
        tables = ",".join("public." + name for name in sorted(schema["SOURCE_TABLES"]))
        connection.exec_driver_sql("LOCK TABLE " + tables + " IN SHARE ROW EXCLUSIVE MODE")
    elif connection.dialect.name != "sqlite":
        raise RuntimeError("Retained read pages require a reviewed database dialect.")
    schema["create_tables"](connection)
    schema["install"](connection)
    schema["backfill"](connection)


def downgrade():
    raise RuntimeError(
        "Matter retained-read projection is restore-forward; restore the reviewed backup."
    )
