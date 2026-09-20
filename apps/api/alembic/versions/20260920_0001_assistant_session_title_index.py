"""Index exact retained assistant-session lookups used by production QA.

DATA-GOVERNANCE-MAP: updated
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260920_0001"
down_revision = "20260913_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "ix_assistant_sessions_company_creator_title"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(
                sa.text(
                    "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                    f"{_INDEX_NAME} ON assistant_sessions "
                    "(company_id, created_by_membership_id, title)"
                )
            )
    else:
        op.create_index(
            _INDEX_NAME,
            "assistant_sessions",
            ["company_id", "created_by_membership_id", "title"],
        )


def downgrade() -> None:
    # Keep rollback transactional so a later evidence-preservation guard can
    # roll back this removal when the requested downgrade is refused.
    op.drop_index(_INDEX_NAME, table_name="assistant_sessions")
