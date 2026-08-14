"""Count matter-import rows skipped as duplicates.

Revision ID: 20260814_0001
Revises: 20260813_0001
Create Date: 2026-08-14

Ram's 14-Aug workbook (BUG-003) reported that duplicate rows are detected but
not excluded from the submission.  Duplicate rows are now a distinct row status
that is skipped rather than rejected, so the job needs its own counter: without
it a duplicate would keep inflating ``invalid_rows`` and the import history
would still read as a failed upload.

Additive and backfilled from the existing rows, so historical jobs report the
same duplicate count they would report if revalidated today.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260814_0001"
down_revision = "20260813_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "matter_bulk_import_jobs",
        sa.Column(
            "duplicate_rows",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    # Historical jobs predate the status, so their rows are all valid/invalid
    # and the backfill correctly leaves the counter at zero.
    op.execute(
        sa.text(
            """
            UPDATE matter_bulk_import_jobs AS j
            SET duplicate_rows = COALESCE(
                (
                    SELECT COUNT(*)
                    FROM matter_bulk_import_rows AS r
                    WHERE r.job_id = j.id AND r.status = 'duplicate'
                ),
                0
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_column("matter_bulk_import_jobs", "duplicate_rows")
